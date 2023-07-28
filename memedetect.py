# #!/usr/bin/env python3
# import numpy as np
# import os
# os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # Set logging level to suppress all messages except error messages
# import tensorflow as tf
# from tensorflow.keras.preprocessing.image import load_img, img_to_array
# from tensorflow.keras.applications.resnet50 import preprocess_input, decode_predictions

# def is_comic_book(path):
#     # Load the pre-trained ResNet50 model
#     model = tf.keras.applications.ResNet50(weights='imagenet')

#     # Load and preprocess the image
#     img = load_img(path, target_size=(224, 224))
#     img_array = img_to_array(img)
#     img_array = np.expand_dims(img_array, axis=0)
#     img_array = preprocess_input(img_array)

#     # Make a prediction
#     predictions = model.predict(img_array)

#     # Decode the predictions
#     predicted_classes = decode_predictions(predictions, top=5)

#     for class_prediction in predicted_classes[0]:
#         print(class_prediction[1], class_prediction[2]*100)

#     # Check if 'comic_book' is in the top 5 predicted classes with a probability of over 50%
#     for class_prediction in predicted_classes[0]:
#         if class_prediction[1] == 'comic_book':  # and class_prediction[2]*100 > 50:
#             return True, class_prediction[2] * 100
#     return False, 0

# # sample = 'sample/test.png'
# # print(sample)
# # print(is_comic_book(sample))